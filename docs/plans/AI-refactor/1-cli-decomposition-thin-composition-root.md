---
summary: "ExecPlan for splitting cookimport/cli.py into command-group modules while preserving the public cookimport CLI surface."
read_when:
  - "When extracting command families out of cookimport/cli.py into cookimport/cli_commands/."
  - "When keeping cookimport.cli:app stable while reducing CLI coordination breadth."
---

# Split `cookimport/cli.py` into command modules behind a thin composition root

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with [docs/PLANS.md](/home/mcnal/projects/recipeimport/docs/PLANS.md).

## Purpose / Big Picture

RecipeImport’s public CLI is the biggest remaining structural bottleneck for safe changes. Right now [cookimport/cli.py](/home/mcnal/projects/recipeimport/cookimport/cli.py) is not only the public entrypoint for `cookimport`, it is also the implementation home for stage execution, Label Studio flows, analytics and dashboard commands, benchmark suite commands, compare-control commands, and interactive mode. That means a contributor trying to change one command family often has to open a file that also owns several unrelated workflows.

After this change, the `cookimport` command should behave the same from the operator’s perspective, but the code should be organized around command families under a new `cookimport/cli_commands/` package. The visible proof is that `cookimport --help`, `cookimport bench --help`, `cookimport labelstudio-benchmark --help`, and the existing command-domain tests still pass, while implementation for each family now lives in one focused module instead of one giant coordinator.

This plan is self-contained. It does not require a parent ExecPlan. It replaces the earlier umbrella planning shape by carrying its own rationale, migration order, validation, and docs duties.

## Progress

- [x] (2026-03-22 16:57 EDT) Re-ran `bin/docs-list` and read `docs/PLANS.md`, `docs/02-cli/02-cli_README.md`, `docs/01-architecture/01-architecture_README.md`, `docs/12-testing/12-testing_README.md`, and `docs/reports/ai-readiness-improvement-report.md`.
- [x] (2026-03-22 16:58 EDT) Audited the current command registration surface in [cookimport/cli.py](/home/mcnal/projects/recipeimport/cookimport/cli.py), including top-level commands, nested `bench` commands, nested `compare-control` commands, and the interactive callback path.
- [x] (2026-03-22 16:59 EDT) Authored this standalone CLI decomposition ExecPlan in `docs/plans/`.
- [x] (2026-03-22 17:30 EDT) Tightened scope and validation after re-checking the live CLI registration tree, including the already-external `epub` sub-app and the need for signature-preservation tests during extraction.
- [x] (2026-03-22 19:05 EDT) Reworked the plan into a burn-the-boats cutover: `cookimport/cli.py` stays only as the public composition root, with moved command implementations deleted from the old file instead of left behind as wrappers.
- [x] (2026-03-23 17:16 EDT) Re-audited the live tree and confirmed `cookimport/cli_commands/` still does not exist, while [cookimport/cli.py](/home/mcnal/projects/recipeimport/cookimport/cli.py) remains a 31,477-line CLI/root coordinator with top-level, bench, compare-control, and interactive ownership still co-located.
- [x] (2026-03-23 17:51 EDT) Created `cookimport/cli_commands/` with extracted command-family modules and folder-local notes; kept the legacy `cookimport/cli.py` runtime wiring in place for now because the current CLI test suite still monkeypatches deep old-module command names.
- [x] (2026-03-23 18:31 EDT) Finished the active cutover: `cookimport/cli.py` now rebuilds the public Typer apps from `cookimport/cli_commands/`, the command modules resync current legacy-module globals before dispatch so CLI monkeypatch tests stay valid, and the CLI docs/folder notes now describe `cli.py` as the composition root rather than the command owner.
- [x] (2026-03-23 20:40 EDT) Redirected the legacy direct-call surface on `cookimport.cli` back to `cookimport/cli_commands/`: each command-family module now returns its registered public callables, and `cookimport/cli.py` re-exports sync wrappers so tests and helper code that still patch `cookimport.cli.<command>` hit the command-package implementation rather than stale in-file copies.

- [x] Create the new `cookimport/cli_commands/` package and establish one module per command family.
- [x] Move the `stage` command implementation behind the new package while keeping `cookimport.cli:app` stable.
- [x] Move the Label Studio command family behind the new package.
- [x] Move analytics, compare-control, and bench command families behind the new package.
- [x] Move interactive-mode orchestration behind the new package while preserving current behavior and `cli_ui` integration.
- [x] Add or update CLI boundary tests and CLI docs for the new ownership map.

## Surprises & Discoveries

- Observation: the CLI file is not merely large; it is the accidental meeting point for several public products.
  Evidence: [cookimport/cli.py](/home/mcnal/projects/recipeimport/cookimport/cli.py) currently registers top-level stage/import/report commands, Label Studio commands, dashboard/perf commands, compare-control commands, bench subcommands, and interactive mode bootstrap in one module.

- Observation: the repo already demonstrates the preferred migration style in one adjacent package.
  Evidence: [cookimport/cli_ui](/home/mcnal/projects/recipeimport/cookimport/cli_ui) already isolates interactive menu and settings helper logic, which means the refactor can extend an existing repo convention instead of inventing a new one.

- Observation: not every CLI surface needs to move as part of this refactor.
  Evidence: `cookimport/cli.py` registers `epub_app` from `cookimport.epubdebug.cli`; that sub-app is already externally owned and should be preserved as a passthrough registration rather than being pulled into `cookimport/cli_commands/`.

- Observation: this refactor is mostly local and should not require token-spending validation.
  Evidence: the affected surfaces are command wiring, help output, and local orchestration boundaries; routine proof should come from CLI and domain test slices plus command help rendering.

- Observation: some former CLI-local responsibilities have already moved out, but that was not enough to shrink the CLI root itself.
  Evidence: [cookimport/cli.py](/home/mcnal/projects/recipeimport/cookimport/cli.py) now imports shared job planning from [cookimport/staging/job_planning.py](/home/mcnal/projects/recipeimport/cookimport/staging/job_planning.py), yet the command registration and command-family implementations are still concentrated in the same file.

## Decision Log

- Decision: keep `cookimport.cli:app` as the public entrypoint.
  Rationale: the goal is to narrow internal interfaces, not to change `pyproject.toml` entrypoints or force workflow retraining.
  Date/Author: 2026-03-22 / Codex

- Decision: create one command-group module per major family under `cookimport/cli_commands/`.
  Rationale: grouping by public capability is easier for newcomers to navigate than slicing by incidental helper category.
  Date/Author: 2026-03-22 / Codex

- Decision: extract command families in order of traffic and coupling: stage, Label Studio, analytics/reporting, compare-control, bench, then interactive mode.
  Rationale: this order reduces the highest supervision cost earliest while keeping the trickiest interactive state migration until the supporting seams already exist.
  Date/Author: 2026-03-22 / Codex

- Decision: complete each command-family move as a real cutover, not a long-lived wrapper migration.
  Rationale: the final goal is a genuinely thin composition root. Temporary extraction scaffolding is acceptable inside one implementation pass, but the checked-in end state must delete moved command implementations from `cookimport/cli.py`.
  Date/Author: 2026-03-22 / Codex

- Decision: treat the existing `epub` sub-app registration as explicitly out of scope for this plan unless implementation uncovers a concrete CLI-root coupling problem.
  Rationale: the goal is to decompose code owned by `cookimport/cli.py`, not to re-home a sub-app that already lives in its own package.
  Date/Author: 2026-03-22 / Codex

## Outcomes & Retrospective

This plan is materially closer to done than the initial extraction audit suggested. The public Typer tree and the legacy direct-call compatibility surface on `cookimport.cli` are now both sourced from `cookimport/cli_commands/`, which means stage/bench/analytics/Label Studio command edits can start in the command-family modules instead of the old root file.

The remaining debt is dead legacy command bodies still present in `cookimport/cli.py`. They are no longer the active runtime or direct-call owner, but the file is still larger than this plan’s ideal end state and should eventually have those stale copies deleted outright.

## Context and Orientation

The current public entrypoint is [cookimport/cli.py](/home/mcnal/projects/recipeimport/cookimport/cli.py). It defines `app = typer.Typer(...)`, nested `bench_app`, nested `compare_control_app`, and many decorated command functions. It also contains the no-subcommand interactive callback. In this repo, “composition root” means the file that instantiates the Typer apps and wires them together. A healthy composition root should mostly define the public command tree and delegate immediately to the owning command module. It should not be the main home of the workflow implementation.

The current command families are visible directly from the registration lines in `cookimport/cli.py`. The file adds nested apps via `app.add_typer(bench_app)` and `app.add_typer(compare_control_app, name="compare-control")`, and it also passes through the externally owned `epub` sub-app via `app.add_typer(epub_app, name="epub")`. It then defines top-level commands such as `stage`, `perf-report`, `stats-dashboard`, `labelstudio-import`, `labelstudio-export`, `labelstudio-eval`, `debug-epub-extract`, and `labelstudio-benchmark`. The bench group defines commands such as `speed-discover`, `speed-run`, `speed-compare`, `quality-discover`, `quality-run`, `quality-compare`, and `quality-leaderboard`. All of that lives beside interactive mode and many utility helpers.

The target package layout for this plan is:

- `cookimport/cli_commands/__init__.py`
- `cookimport/cli_commands/stage.py`
- `cookimport/cli_commands/labelstudio.py`
- `cookimport/cli_commands/analytics.py`
- `cookimport/cli_commands/bench.py`
- `cookimport/cli_commands/compare_control.py`
- `cookimport/cli_commands/interactive.py`

Each module should own one public family. “Own” here means it becomes the first place a reader opens to understand or modify that family. By the completed end state, moved command implementations must no longer live in `cookimport/cli.py`. The old file remains only because the CLI entrypoint still needs one composition root.

This plan does not move `cookimport.epubdebug.cli`. The `epub` sub-app should remain registered from the composition root exactly as it is today unless a later, separate plan is created for that package.

The module contracts should be simple:

    def register(app: typer.Typer) -> None: ...

for top-level families, and:

    def build_app() -> typer.Typer: ...

for nested sub-app families such as `bench` or `compare-control`.

The point is progressive disclosure. A newcomer should first open `cookimport/cli_commands/bench.py` for bench behavior, not search a giant shared file for `@bench_app.command`.

## Milestones

### Milestone 1: Create the new CLI command package and registration skeleton

At the end of this milestone, the repo will contain the `cookimport/cli_commands/` package with one module per command family. This milestone may use short-lived extraction scaffolding while work is in progress, but the finished milestone state should already remove at least one real command-family implementation from `cookimport/cli.py`.

Acceptance is that the new package exists, the public entrypoint remains `cookimport.cli:app`, and current help output still renders.

### Milestone 2: Move stage and Label Studio commands behind the new package

At the end of this milestone, the highest-value public command families will be routed through `cookimport/cli_commands/stage.py` and `cookimport/cli_commands/labelstudio.py`. The moved command bodies should be deleted from `cookimport/cli.py`; that file should retain only the registration/composition code required by Typer for those commands. This milestone is where the first meaningful drop in coordination breadth appears.

Acceptance is that stage and Label Studio command tests still pass, help output still matches expected command names, and contributors can now modify those commands by starting in the new modules.

### Milestone 3: Move analytics, compare-control, and bench command families

At the end of this milestone, the nested app families and analytics/reporting commands will live in their own modules. `cookimport/cli.py` should no longer be the first place to inspect for these public surfaces. The `bench` module should own the nested bench Typer app builder, and `compare_control.py` should own the compare-control app builder.

Acceptance is passing CLI and bench-domain validation plus the same public command tree as before.

### Milestone 4: Move interactive orchestration behind the new package

At the end of this milestone, no-subcommand interactive mode will be bootstrapped from `cookimport/cli_commands/interactive.py`, even if it continues to reuse helpers under `cookimport/cli_ui/`. Interactive mode is left until late because it still touches several settings, prompts, and callback helpers. The goal is not to redesign the interactive flow. The goal is to give it one obvious owner outside the composition root.

Acceptance is that running `cookimport` with no subcommand still enters interactive mode and the current CLI help behavior remains unchanged.

### Milestone 5: Add boundary tests and update docs

At the end of this milestone, the new ownership map is protected by tests and taught in docs. Add CLI registration tests or smoke tests that make it hard to accidentally collapse unrelated command families back into one file. Also add signature-alignment tests for adapter-driven commands that are most likely to drift during extraction. Update [docs/02-cli/02-cli_README.md](/home/mcnal/projects/recipeimport/docs/02-cli/02-cli_README.md) and the architecture readme so they point readers toward the new command package instead of treating `cookimport/cli.py` as the universal source of truth.

Acceptance is that `bin/docs-list` shows the updated docs, and the tests fail narrowly if future edits break the command boundary.

## Plan of Work

Start by creating the package skeleton under `cookimport/cli_commands/`. Add the module files and define explicit registration helpers. Then update `cookimport/cli.py` so it imports those helpers and uses them to register command families. Any extraction scaffolding used while editing should be removed before the milestone is considered complete. The crucial rule is that `cookimport/cli.py` must end each completed milestone with less real command implementation than before, not with a growing pile of wrappers.

Move the command families incrementally. Start with `stage`, because it is the most important public command and the clearest example of why the composition root should stay thin. Then move the Label Studio family, which is a major public surface and one of the next-largest cognitive loads in the file. After that, move analytics and compare-control, which are logically distinct and easy wins for navigation. Then move the nested bench app, which benefits from having its own module but may touch more helper code. Finally, move interactive orchestration. Keep `epub_app` untouched in the composition root throughout; that registration is already as thin as it needs to be.

As each family moves, add or update tests immediately. The right pattern is to capture the command registration boundary at the same time the code boundary appears. Do not postpone tests until the whole CLI split is complete. Also update docs progressively: once a family is truly owned by its new module, the CLI docs should say so.

When moving decorated command functions, preserve the public function signatures used by existing signature-sync tests and helper call sites, but do not keep duplicate implementations around after the cutover. If one command family needs a bigger extraction, update the tests in the same change set and delete the old body instead of carrying a long-lived bridge.

## Concrete Steps

All commands below run from `/home/mcnal/projects/recipeimport`.

Inspect the current registration surface:

    rg -n "@app\\.command|@bench_app\\.command|@compare_control_app\\.command|add_typer" cookimport/cli.py

    sed -n '240,340p' cookimport/cli.py

Create the new module set with `apply_patch`:

    cookimport/cli_commands/__init__.py
    cookimport/cli_commands/stage.py
    cookimport/cli_commands/labelstudio.py
    cookimport/cli_commands/analytics.py
    cookimport/cli_commands/bench.py
    cookimport/cli_commands/compare_control.py
    cookimport/cli_commands/interactive.py

For each migration step:

1. Move one command family’s implementation into the owning module.
2. Remove the moved command implementation from `cookimport/cli.py` once registration is wired through the new module.
3. Run a narrow test loop.
4. Run the broader CLI or bench wrapper.
5. Update docs if that module is now authoritative.
6. Confirm `epub` passthrough registration remains unchanged.

Prepare the environment if needed:

    . .venv/bin/activate
    pip install -e .[dev]

Use narrow test loops intentionally:

    . .venv/bin/activate
    pytest tests/cli -k "stage or labelstudio or interactive"

    . .venv/bin/activate
    pytest tests/bench -k "cli or speed or quality"

Routine broader validation should use wrappers:

    . .venv/bin/activate
    ./scripts/test-suite.sh domain cli

    . .venv/bin/activate
    ./scripts/test-suite.sh domain bench

    . .venv/bin/activate
    ./scripts/test-suite.sh fast

Confirm help surfaces after major moves:

    . .venv/bin/activate
    cookimport --help

    . .venv/bin/activate
    cookimport bench --help

    . .venv/bin/activate
    cookimport compare-control --help

    . .venv/bin/activate
    cookimport epub --help

## Validation and Acceptance

Acceptance is behavioral first. The public command tree must remain stable. Existing top-level and nested commands must keep their current names and basic invocation shape. A user should not notice the refactor from normal CLI usage.

The second acceptance criterion is navigability. After the refactor, a newcomer should be able to open one command module and understand the implementation surface for that family without reading unrelated command families. `cookimport/cli.py` should become a thin registration layer.

The third acceptance criterion is local proof. The relevant narrow CLI test slices must pass, including signature-sync tests for adapter-driven commands, followed by `./scripts/test-suite.sh domain cli`, `./scripts/test-suite.sh domain bench` for bench moves, and then `./scripts/test-suite.sh fast` before declaring the migration stable.

The fifth acceptance criterion is final-state deletion. Moved command implementations must be gone from `cookimport/cli.py`; the file should remain only as the public Typer composition root plus the explicitly out-of-scope `epub` passthrough registration.

The fourth acceptance criterion is documentation. `docs/02-cli/02-cli_README.md` and any touched architecture docs must point readers to the new command package rather than treating `cookimport/cli.py` as the only source of truth.

## Idempotence and Recovery

This refactor is safe to do incrementally, but it is not meant to end in a dual-home state. If one extraction breaks a command during implementation, fix it or temporarily park the work on that family; do not check in a permanent bridge that keeps the old implementation alive beside the new one.

If Typer registration becomes awkward in one module, solve the decorator/registration problem in the same refactor rather than preserving the old command body indefinitely. The goal is to keep the public CLI stable while decisively shrinking the composition root.

## Artifacts and Notes

Keep short evidence snippets here as work proceeds. Examples:

    cookimport --help
    # expected: same top-level command names as before

    cookimport bench --help
    # expected: same bench subcommands as before

    cookimport epub --help
    # expected: existing epub debug subcommands still render because the composition root still registers the external sub-app unchanged

    ./scripts/test-suite.sh domain cli
    # expected: CLI domain slice passes after command-family extraction

## Interfaces and Dependencies

The target interfaces are:

In `cookimport/cli_commands/stage.py`:

    def register(app: typer.Typer) -> None: ...

In `cookimport/cli_commands/labelstudio.py`:

    def register(app: typer.Typer) -> None: ...

In `cookimport/cli_commands/analytics.py`:

    def register(app: typer.Typer) -> None: ...

In `cookimport/cli_commands/bench.py`:

    def build_app() -> typer.Typer: ...

In `cookimport/cli_commands/compare_control.py`:

    def build_app() -> typer.Typer: ...

In `cookimport/cli_commands/interactive.py`:

    def register_callback(app: typer.Typer) -> None: ...

The new command modules may depend on their owning runtime domains and shared config helpers, but they should avoid pulling in unrelated command families. That is the boundary this plan is trying to create.

## Revision note

Created on 2026-03-22 as one of three standalone child ExecPlans replacing the earlier umbrella AI-readiness refactor plan. Updated later the same day after re-checking the live CLI tree and then again to a burn-the-boats posture. Updated on 2026-03-23 after re-auditing the current tree; the plan still applies, but now explicitly notes that other refactors have reduced some adjacent seams without yet creating `cookimport/cli_commands/`.
