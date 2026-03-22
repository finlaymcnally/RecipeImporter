---
summary: "Current repo-specific report on how to improve RecipeImport for AI-assisted development by shrinking coordination surfaces, preserving strong stage/runtime contracts, and finishing the remaining deep-module work."
read_when:
  - "When planning architecture work to make the repo easier for AI agents and new humans to navigate."
  - "When deciding what to split first between CLI, shared stage/prediction planning, and run settings."
  - "When translating a general 'deep modules' argument into concrete repo changes for RecipeImport."
---

# AI Readiness Improvement Report

Assessment date: 2026-03-22

This document is the current assessment of RecipeImport as a codebase for AI-assisted development. It is written as the authoritative version for the repo's present architecture, not as a change log of earlier reviews.

The standard used here is the same one described in `docs/reports/AI-codebase.md`, but translated into RecipeImport-specific architecture choices and priorities.

## Scope

Primary docs reviewed:

- `docs/AI_context.md`
- `docs/01-architecture/01-architecture_README.md`
- `docs/02-cli/02-cli_README.md`
- `docs/06-label-studio/06-label-studio_README.md`
- `docs/10-llm/10-llm_README.md`
- `docs/12-testing/12-testing_README.md`
- `docs/reports/2026-03-13-run-settings-surface-audit.md`
- `cookimport/config/CONVENTIONS.md`

Primary code surfaces spot-checked:

- `cookimport/cli.py`
- `cookimport/cli_worker.py`
- `cookimport/staging/import_session.py`
- `cookimport/labelstudio/ingest.py`
- `cookimport/config/run_settings.py`
- `cookimport/config/run_settings_adapters.py`
- `cookimport/config/codex_decision.py`
- `cookimport/runs/stage_observability.py`
- `cookimport/llm/codex_exec_runner.py`

Current size snapshots that matter for this review:

- `cookimport/cli.py`: `31,834` lines
- `cookimport/analytics/dashboard_render.py`: `14,535` lines
- `cookimport/parsing/canonical_line_roles.py`: `8,297` lines
- `cookimport/labelstudio/ingest.py`: `4,052` lines
- `cookimport/bench/quality_runner.py`: `3,136` lines
- `cookimport/config/run_settings.py`: `2,010` lines
- `cookimport/staging/import_session.py`: `783` lines
- `cookimport/cli_worker.py`: `654` lines

## Executive summary

RecipeImport is already better than most repos for AI-assisted work because it has unusually strong local documentation, clear staged artifact contracts, fast scoped tests, and several real runtime seams.

Its main remaining weakness is structural rather than informational. The repo explains itself well, but too much safe-change knowledge is still concentrated in a few very large coordinators and in a handful of cross-file coordination rules. In practice, that means AI can often succeed here by reading a lot and relying on tests, but it still cannot stay inside a small enough interface as often as it should.

The central conclusion is the same as the general report: codebase structure matters more than prompting. RecipeImport is already documented well enough for an AI to orient itself. The next gains come from reducing how much code an agent has to open before it can make one safe change.

Current rating for the specific deep-modules / AI-readiness standard: roughly `7.25/10`.

That is a solid score. It means the repo is clearly AI-usable and increasingly AI-friendly. It does not yet mean the repo is fully AI-shaped.

## What "AI-friendly" means in this repo

For this review, a codebase is AI-friendly when an agent can do four things quickly and reliably:

1. find the relevant area of the system,
2. understand that area's public contract without reading all of its internals,
3. make a local change without accidentally pulling in unrelated concerns,
4. verify the result through fast, trustworthy feedback.

This is another way to say: treat AI as a constant stream of new starters. Every session begins with limited context, no lived memory, and a short window to form a correct mental model. A repo that works well for that kind of contributor usually works well for a fresh human too.

For RecipeImport, that means the ideal shape is:

- docs and folder structure that mirror the real product domains,
- deep modules with small explicit interfaces,
- progressive disclosure from docs and public entrypoints into internals,
- tests that lock down boundary behavior,
- a small number of enforced rules that stop accidental cross-domain drift.

The repo is already good on the first and fourth bullets. The biggest remaining work is on the second, third, and fifth.

## What the repo already does well

### 1. The docs are unusually strong

This repo has one of the biggest advantages an AI tool can have: a maintained local knowledge base that actually reflects the current system.

The strongest examples are:

- `docs/AI_context.md` for fast orientation,
- `docs/01-architecture/01-architecture_README.md` for runtime shape and authority boundaries,
- the numbered subsystem READMEs for ownership by domain,
- `docs/12-testing/12-testing_README.md` for the real test-running contract instead of generic `pytest` advice.

This matters because the model can start from explicit architecture and artifact contracts instead of reconstructing the repo from imports and guesswork.

This is a major part of progressive disclosure already working. A fresh agent can usually start with the right docs before reading implementation.

### 2. Stage and runtime contracts are much clearer than average

Several important seams are explicit and valuable:

- semantic `stage_observability.json` is the run-level stage naming backbone,
- label-first staged artifacts are the recipe/non-recipe authority seam,
- `cookimport/staging/import_session.py` is a real shared stage-session boundary,
- Codex-backed worker flows use explicit repo-written files such as `worker_manifest.json` and `current_task.json`.

These are the kinds of contracts that make AI work safer because they reduce hidden topology and clarify what downstream tools should trust.

That is exactly the right direction: small authority seams with explicit artifacts instead of "just know which helper to call."

### 3. The test structure supports safe iteration

The test system is meaningfully better than average for AI-assisted loops:

- domain-oriented folders,
- centralized marker routing,
- a real smoke lane,
- wrapper scripts for routine runs,
- intentionally compact output to keep feedback readable.

That is exactly the kind of setup that makes broad code reading less necessary because the repo can validate narrow changes quickly.

The repo already treats tests as a real feedback loop instead of a last-step ceremony, which is one of the strongest predictors of safe AI iteration.

### 4. The repo has some genuine deep seams already

This codebase is not missing architectural discipline. It already contains several promising interfaces:

- importer selection behind `cookimport/plugins/base.py`,
- semantic stage reporting in `cookimport/runs/stage_observability.py`,
- settings-to-runtime mapping in `cookimport/config/run_settings_adapters.py`,
- shared stage-session execution in `cookimport/staging/import_session.py`.

The problem is not a total absence of good seams. The problem is that those seams are still not dominant enough to keep the highest-traffic workflows narrow.

In other words, RecipeImport has promising deep modules, but some of the busiest workflows still route around them.

## Where the repo is still fighting the deep-modules goal

### 1. `cookimport/cli.py` is still the single biggest architectural bottleneck

`cookimport/cli.py` is `31,834` lines and still owns too much of the operator-facing system:

- command wiring,
- interactive flows,
- stage orchestration,
- benchmark orchestration,
- report generation,
- dashboard and analytics entrypoints,
- Label Studio handoff logic,
- helper and summary utilities.

This is still the widest supervision surface in the repo. If one thing most directly limits “fresh agent can make a safe change after reading only a few files,” it is this file.

It also violates the strongest rule from the general report: the composition root should stay thin. Right now the composition root, operator surface, workflow planner, and a large pile of helpers still live too close together.

### 2. Shared planning logic is still duplicated across top-level flows

The repo has a good shared session seam in `cookimport/staging/import_session.py`, but planning and execution-prep logic still forks too early.

The clearest examples are:

- `cookimport/cli.py:_plan_jobs(...)`
- `cookimport/labelstudio/ingest.py:_plan_parallel_convert_jobs(...)`
- `cookimport/config/run_settings.py:compute_effective_workers(...)`

The conventions doc still has to teach alignment rules such as:

- update both planners together,
- propagate extractor and parser settings through both stage and prediction paths,
- keep multiple report and manifest surfaces aligned.

That is exactly the kind of hidden breadth that hurts AI assistance. A repo is much easier to work in when “change the rule once” is the default instead of “remember all the places.”

This is a classic failure of interface design rather than documentation. The repo already documents the alignment rule, but the code should make that rule hard to violate.

### 3. `RunSettings` is still structurally overloaded

The repo clearly understands that the real product surface is smaller than the total persistence surface. That understanding already appears in docs, adapters, and interactive profile logic.

But the data model is still one broad `RunSettings` class with `71` annotated fields spanning:

- product choices,
- benchmark and tuning knobs,
- runtime internals,
- compatibility and persistence baggage.

That keeps too much cognitive load in one place. A fresh human or AI still has to learn one oversized object before fully understanding which settings are real operator intent and which ones are lab or implementation seams.

The general report's framing fits exactly here: public interfaces should be small, typed, stable, and hard to misuse. `RunSettings` still mixes multiple audiences into one object, so the effective interface is bigger than it needs to be.

### 4. Several domains still bottleneck through very large files

Beyond `cli.py`, the repo still has other files large enough to create local architecture bottlenecks:

- `cookimport/analytics/dashboard_render.py`: `14,535` lines
- `cookimport/parsing/canonical_line_roles.py`: `8,297` lines
- `cookimport/labelstudio/ingest.py`: `4,052` lines
- `cookimport/bench/quality_runner.py`: `3,136` lines
- `cookimport/config/run_settings.py`: `2,010` lines

Large files are not automatically bad. The problem is when the effective interface becomes “open the giant file and read around” rather than “read the command or contract, then inspect one bounded implementation area.”

That is the practical difference between a deep module and a giant coordinator. Both can be large internally. Only one gives a newcomer a narrow place to stand.

### 5. Package layering is still weaker than the folder structure suggests

A quick import-graph scan still shows mutual package relationships such as:

- `bench <-> config`
- `core <-> parsing`
- `labelstudio <-> llm`
- `labelstudio <-> parsing`
- `labelstudio <-> staging`
- `llm <-> parsing`
- `llm <-> runs`
- `llm <-> staging`

Not all of these are equally harmful, but together they weaken module depth. The issue is not whether the graph is mathematically pure. The issue is that it is still too easy for one subsystem to know too much about another.

This is where "organize around capabilities, not technical fragments" matters. RecipeImport's folders already suggest real domains, but some dependency edges still act like a technical-layer web rather than a capability map.

### 6. The optional LLM subsystem is clearer, but still heavy

The current worker/session contracts are better specified than average, which is good. But the operational surface around:

- workspace workers,
- watchdog behavior,
- retry and repair ladders,
- task manifests,
- stage summaries,
- promotion artifacts

is substantial enough that LLM-path work still requires a lot of local context.

That is not an argument to undo the current architecture. It is an argument to preserve the newer explicit contracts and avoid letting more top-level coordination logic leak around them.

The LLM area is a good example of why the goal is not tiny modules everywhere. It needs deep internal machinery. The important part is keeping the public operational surface explicit and keeping unrelated domains from reaching into those internals.

### 7. Shared helpers and cross-cutting rules still need tighter ownership

The repo is not dominated by a `utils/` junk drawer, which is good. But some coordination still behaves like shared utility sprawl even when it is not physically stored in one directory:

- duplicated planner logic across CLI and Label Studio flows,
- broad settings objects used by many domains,
- conventions docs that carry rules the code should eventually enforce.

That kind of spread is dangerous for AI work because it makes a local change look deceptively global. The repo does not need more generic helpers. It needs clearer ownership of the few cross-cutting seams it already has.

## Recommendations

### Recommendation 1: Split `cookimport/cli.py` by responsibility

This should be the top structural priority.

The goal is not to win on line count. The goal is to stop using one file as the meeting point for:

- command registration,
- interactive UI flows,
- execution orchestration,
- benchmark helpers,
- output and report formatting.

The right target is:

- a thin app/composition root,
- command-group modules,
- interactive helpers separated from non-interactive command handlers,
- shared runtime/services called from those modules.

The important design rule is progressive disclosure:

- first read the command-group entrypoint,
- then the local types or helper contracts,
- only then the deeper implementation if needed.

This is still the single highest-leverage change for AI-readiness in the repo.

### Recommendation 2: Extract one shared planning seam for stage and prediction flows

The repo already has a shared session seam. What it still needs is one shared planning and execution-prep boundary for:

- split-job planning,
- effective-worker resolution,
- per-source execution planning,
- merge-oriented job metadata.

If that seam exists, the conventions doc no longer needs to encode “update both planners together” as an architectural rule.

The boundary should be treated as a first-class public interface:

- one planning input model,
- one worker-resolution policy surface,
- one output/job-plan contract,
- boundary tests that prove both top-level flows use the same semantics.

That would turn a memorized coordination rule into a code-enforced seam.

### Recommendation 3: Make config layering first-class in code

The repo has already done the conceptual work. The next step is to represent that split directly in code with clearer layers such as:

- operator-facing choices,
- benchmark/lab overrides,
- resolved runtime config,
- hidden/internal persistence.

The lower-effort version is still valid:

- keep `RunSettings` as storage for now,
- make the projections authoritative,
- keep most summaries and UIs on the smaller operator-facing contract,
- add tests that lock the projection boundaries.

This follows the same principle as the general report's `public.ts` idea: most callers should not have to understand the entire persistence object to use config correctly.

### Recommendation 4: Add a small set of boundary tests

The test story is already strong enough to support architectural tightening.

High-value boundary tests would cover:

- shared split planning behavior,
- run-settings projection behavior,
- semantic stage observability and artifact contracts,
- a small set of prohibited package edges.

This repo does not need a heavy architecture-enforcement system. It does need a few locks that prevent silent drift back toward hidden breadth.

### Recommendation 5: Make module ownership more visible in the filesystem and docs

When a domain is touched during refactors, prefer a shape that makes the module boundary obvious:

- short local README plus doc link for purpose and invariants,
- one obvious entrypoint per command group or service,
- internals grouped under the owning domain instead of drifting into generic shared space.

RecipeImport does not need to mechanically adopt `public.ts` or `internal/` naming. It does need the same effect: outsiders should be able to tell what is safe to depend on and what is implementation detail.

### Recommendation 6: Only after that, break up the next-largest bottlenecks

Once the command, runtime, and config seams are clearer, then it becomes worth shrinking the next bottlenecks:

- `cookimport/analytics/dashboard_render.py`
- `cookimport/parsing/canonical_line_roles.py`
- `cookimport/labelstudio/ingest.py`
- `cookimport/config/run_settings.py`

Doing these earlier risks creating many smaller shallow files without actually reducing supervision cost.

The rule from the general report applies here: avoid replacing one big understandable file with a web of tiny cross-coupled files. Split only when the new boundary is real.

## Practical migration approach

The safest path is incremental:

1. start with the highest-churn boundary, not with a repo-wide reorg,
2. define the public seam before moving large amounts of implementation,
3. add boundary tests before or alongside extraction,
4. enforce only the few dependency rules that protect the new seam,
5. repeat in the next high-traffic area.

For RecipeImport, that means:

1. `cli.py` into command groups plus a thin composition root,
2. shared planning seam for stage and prediction/import flows,
3. config projections made authoritative,
4. only then attack the next-largest coordinators.

## Priority order

If only three structural improvements happen next, they should be:

1. split `cookimport/cli.py` into command modules plus a thin composition root,
2. extract one shared planning seam used by both stage and Label Studio prediction/import flows,
3. make the operator/lab/internal config split first-class in code and tests.

Those three changes would do the most to reduce repo-wide context loading for both humans and AI.

## Final assessment

RecipeImport is a good and increasingly AI-friendly codebase.

Its strengths are real:

- strong docs,
- explicit stage and artifact contracts,
- useful test slicing,
- several genuine runtime seams.

Its remaining blockers are also clear:

- giant coordinators,
- duplicated planning seams,
- one overloaded run-settings model,
- weak layering in a few high-traffic domains.

The right framing for the next phase is not “make the repo more modular” in the abstract. It is:

"Reduce the amount of repo-wide context needed to make one safe change."

That is the shortest path from a good-but-complex codebase to one that is genuinely easier for both humans and AI to supervise.

The repo does not need a brand-new architecture style. It needs its existing good ideas to become the default way work is shaped:

- docs first,
- narrow public seams,
- deep implementations behind those seams,
- fast boundary feedback,
- fewer places where "remember the coordination rule" substitutes for an explicit interface.
