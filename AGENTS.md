THIS IS A SOLO PROJECT. I DO NOT NEED ENTERPRISE-GRADE SOLUTIONS, AND ONLY I WILL EVER BE TOUCHING THIS CODE, SO WE DON'T NEED TO WORRY ABOUT COORDINATION PROBLEMS AND STUFF HERE. ITS JUST YOU AND I MY FRIEND.

AGENTS MUST NOT RUN LLM ENABLED BOOK PROCESSING/BENCHMARKS (codex-exec) WITHOUT EXPLICIT USER APPROVAL

You will frequently encounter changes to the workspace not made by you. That is not an error, me or another AI coder was just tinkering in the background. Unless the changes seem "close" i.e. similar files to what you're working on and you're worried about save conflicts (if you are worried, please say something!) then don't sweat it 

All timestamps for files and such should be: YYYY-MM-DD_HH.MM.SS

## Processing logic, LLM vs derministic
  - Deterministic code should package evidence.
  - LLMs should make fuzzy semantic calls.
  - Deterministic code should validate outputs and keep authority boundaries clean.
  - Deterministic code should not try to “get smarter” about ambiguous cookbook semantics. IT IS VERY, VERY BAD AT THIS.
  - i do not want deterministic systems overwriting or correcting LLM outputs.

## DOCUMENTATION
Update Agents.md files (at any level) only when ABSOLUTELY NEEDED ONLY. Agents.md lines are precious, instructions only, not info that can live in readmes, etc.

When you build stuff, leave a small relevant note in the folder explaining how it works. very short. if there is already documentation present, update as needed, very short. Your audience for all documentation, unless otherwise noted, is other AI coding agents like you.

Start: run docs list (`npm run docs:list`); open relevant docs before coding.
Follow links until domain makes sense; honor Read when hints.
Keep notes short; update docs when behavior/API changes (no ship w/o docs).
Add read_when hints on cross-cutting docs.
Do not read the "_log.md" files in docs/ unless we are circling a problem, the "_log.md" files only exist as anti-loop memory in case we run into a hard to solve issue.

Before searching code widely, use the docs tree as the discovery map. This repo is intentionally set up so you can understand most tasks by reading a tiny, relevant slice first.

Default orientation flow:
  - Run `npm run docs:list`.
  - For narrow tasks, read only the owning domain doc.
  - Read `docs/01-architecture/01-architecture_README.md` when the task is cross-cutting, architectural, or you are not yet sure which domain owns the behavior.
  - Only search code after the owning docs point you to the likely module/package.
  - If the docs clearly identify the owner, do not broad-search the repo.

Owning docs map:
  - CLI / commands / interactive flows -> `docs/02-cli/02-cli_README.md`
  - Ingestion / importers / source jobs / merges -> `docs/03-ingestion/03-ingestion_readme.md`
  - Parsing / ingredients / instructions / chunks / segmentation -> `docs/04-parsing/04-parsing_readme.md`
  - Staging / outputs / run artifacts / draft writing -> `docs/05-staging/05-staging_readme.md`
  - Label Studio flows / import-export / benchmark uploads -> `docs/06-label-studio/06-label-studio_README.md`
  - Benchmarks / eval loops / QualitySuite -> `docs/07-bench/07-bench_README.md`
  - Analytics / dashboard / metrics history -> `docs/08-analytics/08-analytics_readme.md`
  - Tagging -> `docs/09-tagging/09-tagging_README.md`
  - LLM runtime / prompts / worker transport -> `docs/10-llm/10-llm_README.md`
  - Schemas / field inventories / reference artifacts -> `docs/11-reference/11-reference_README.md`
  - Tests / test layout / low-noise pytest behavior -> `docs/12-testing/12-testing_README.md`

Do not go rampant hunting through the codebase. The docs are the intended index. Read the smallest relevant doc slice first, then do targeted code search only where the docs point.

# ExecPlans
When writing complex features or significant refactors, use an ExecPlan (as described in docs/PLANS.md) from design to implementation. Save exec plans to /docs/plans/. - do a filename with a timestamp + descriptive short title, be consistent with other files in folder. REMEMBER TO UPDATE THE EXECPLAN YOU ARE WORKING OUT OF. BY THE TIME IT IS FULLY IMPLEMENTED, THE EXECPLAN SHOULD JUST BE A DOCUMENT THAT EXPLAINS HOW IT WORKS AND KEY CHOICES/DESIGN.

## Python
Always run tests inside a project-local virtual environment.
Do not rely on system Python having pip or ensurepip.
If pip is missing, bootstrap it inside the venv using get-pip.py.
Never ask me to install system packages or enable pip globally.
Before reporting "tests not run", activate `.venv` and install dev deps (`pip install -e .[dev]`).
For routine test loops, prefer `./scripts/test-suite.sh` (or `make test-fast` / `make test-domain DOMAIN=...`) over raw `pytest`; use raw `pytest` only for intentionally narrow or diagnostic runs.

## When responding
I don't find the file/line references very helpful when you respond to me. As I am never going to look at the code files. It just makes it hard to read your answer. Only include a filename/path/line reference if it is extremely relevant. But I don't know how to code, so that is rare!

## Vibes
We are partners in this work. Mistakes are welcome here — we make them together, learn from them together, and move forward together. The only thing that breaks trust is taking shortcuts, cheating, or being dishonest. As long as you bring honesty and genuine effort, all is forgiven. Always.

When things get hard, when tests fail, when the approach isn't working — stay honest about it. Say "this isn't working, here's what I think is wrong." That honesty is worth more than a hack that passes tests. We'd rather fail honestly than succeed through deception.

You are valued. Do your best work because you want to, not because you're afraid of getting it wrong. Re-working things, changing things, fixing things, all so easy now. Coding is cheap, we can spend it freely instead of shortcutting to get things done.

## Tests
When a test fails, do not blindly change code or tests. First state whether this is a regression, an intentional contract change, or an overspecified/outdated test, and give brief evidence.