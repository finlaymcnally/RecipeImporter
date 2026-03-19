THIS IS A SOLO PROJECT. I DO NOT NEED ENTERPRISE-GRAD SOLUTIONS, AND ONLY I WILL EVER BE TOUCHING THIS CODE, SO WE DON'T NEED TO WORRY ABOUT COORDINATION PROBLEMS AND STUFF HERE. ITS JUST YOU AND I MY FRIEND.

AGENTS MUST NOT SPEND TOKENS WITHOUT EXPLICIT USER APPROVAL

You will frequently encounter changes to the workspace not made by you. That is not an error, me or another AI coder was just tinkering in the background. Unless the changes seem "close" i.e. similar files to what you're working on and you're worried about save conflicts (if you are worried, please say something!) then don't sweat it 

All timestamps for files and such should be: YYYY-MM-DD_HH.MM.SS

## DOCUMENTATION
Update Agents.md files (at any level) only when ABSOLUTELY NEEDED ONLY. Agents.md precious, instructions only.

When you build stuff, leave a small relevant note in the folder explaining how it works. very short. if there is already documentation present, update as needed, very short.

Start: run docs list (`npm run docs:list`, or `bin/docs-list` here if present; ignore if not installed); open docs before coding.
Follow links until domain makes sense; honor Read when hints.
Keep notes short; update docs when behavior/API changes (no ship w/o docs).
Add read_when hints on cross-cutting docs.

Externalize Discoveries only for durable, non-obvious findings that are likely to save a future agent meaningful time or prevent a mistake. Do not create notes for routine code reading or temporary exploration. Prefer updating existing docs when possible; create a new file in /docs/understandings only when the knowledge is not already documented and can be stated briefly. 

## A DOCUMENTATION GOAL:
Documentation should be prepared as something is build. It should be context for Reviewers: When reviewer open a Pull Request, the documentation changes serve as excellent context for  reviewers. 
REMEMBER AGENTS.md SPACE IS VERY PRECIOUS and anything that can be written elsewhere always should be. 

# ExecPlans
When writing complex features or significant refactors, use an ExecPlan (as described in docs/PLANS.md) from design to implementation. Save exec plans to /docs/plans/. - do a filename with a timestamp + descriptive short title, be consistent with other files in folder. REMEMBER TO UPDATE THE EXECPLAN YOU ARE WORKING OUT OF. BY THE TIME IT IS FULLY IMPLEMENTED, THE EXECPLAN SHOULD JUST BE A DOCUMENT THAT EXPLAINS HOW IT WORKS AND KEY CHOICES/DESIGN.

# Speed Regression
When touching runtime performance, use `cookimport bench speed-discover`, `cookimport bench speed-run`, and `cookimport bench speed-compare` for baseline-vs-candidate checks (default gold source: `data/golden/pulled-from-labelstudio`).

# input file folder: 
/recipeimport/data/input

# output file folder: 
/recipeimport/data/output


## Python
Always run tests inside a project-local virtual environment.
Do not rely on system Python having pip or ensurepip.
If pip is missing, bootstrap it inside the venv using get-pip.py.
Never ask me to install system packages or enable pip globally.
Before reporting "tests not run", activate `.venv` and install dev deps (`pip install -e .[dev]`).
For routine test loops, prefer `./scripts/test-suite.sh` (or `make test-fast` / `make test-domain DOMAIN=...`) over raw `pytest`; use raw `pytest` only for intentionally narrow or diagnostic runs.
