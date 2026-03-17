# Recipe Codex Home

This file explains how RecipeImport forces CodexFarm to use the dedicated recipe Codex profile.

## What this is

This is the RecipeImport -> CodexFarm session-isolation seam.

The goal is simple: when RecipeImport launches CodexFarm, it should use `~/.codex-recipe` instead of silently inheriting the main `~/.codex` profile.

## Where it lives

The behavior lives in `codex_farm_runner.py`, because every real CodexFarm subprocess in this repo flows through that runner.

That includes:
- recipe correction
- knowledge harvest
- canonical line-role runs
- freeform prelabel runs
- helper/discovery calls like `codex-farm models list`, `pipelines list`, `run errors`, and `run autotune`

## How it works

`_merge_env(...)` calls `_resolve_recipeimport_codex_home(...)` and injects `CODEX_HOME` plus `CODEX_FARM_CODEX_HOME_RECIPE` before spawning `codex-farm`.

That means the choice is enforced at subprocess-launch time, not by hoping the operator shell happened to export the right value earlier.

Resolution order is:
- explicit subprocess `CODEX_HOME`
- explicit subprocess `CODEX_FARM_CODEX_HOME_RECIPE`
- `COOKIMPORT_CODEX_FARM_CODEX_HOME`
- ambient `CODEX_FARM_CODEX_HOME_RECIPE`
- fallback `~/.codex-recipe`

## Why the runner owns this

RecipeImport's local `llm_pipelines/pipelines/*.json` files do not declare CodexFarm `codex_home_profile` metadata.

Because of that, the most reliable place to force the home is the RecipeImport runner itself. If the runner sets the env every time, the pipeline pack does not need to remember anything special.

## Practical meaning

If RecipeImport launches CodexFarm normally, it should use the dedicated recipe profile without relying on shell aliases or the pipeline pack declaring `codex_home_profile`.

If you are debugging a RecipeImport CodexFarm run and it seems to be using the wrong Codex session, the first place to inspect is `cookimport/llm/codex_farm_runner.py`, not the pipeline JSON.

## Override rule

If you really need a different Codex home for one special call, pass an explicit subprocess env override. That still wins over the default recipe profile.
