---
summary: "Stage-first documentation index for quickly routing AI coders to the right context."
read_when:
  - When starting work with little or no project context
  - When deciding which docs section to read before changing code
---

# Docs Index (Stage-First)

Read by task, not by chronology.

## Quick routing

- CLI and interactive menu behavior: `docs/02-cli/README.md`
- Importing source files (EPUB/PDF/Excel/Text/Paprika/RecipeSage): `docs/03-ingestion/README.md`
- Parsing (ingredients, instructions, step-linking, tips, chunks): `docs/04-parsing/README.md`
- Output shaping and staging contracts: `docs/05-staging/README.md`
- Label Studio import/export/eval workflows: `docs/06-label-studio/README.md`
- Offline benchmark suite: `docs/07-bench/README.md`
- Metrics/performance/dashboard: `docs/08-analytics/README.md`
- Catalog-driven auto-tagging: `docs/09-tagging/README.md`
- Optional LLM repair layer: `docs/10-llm/README.md`
- Schemas and field inventories: `docs/11-reference/README.md`

## Architecture and cross-cutting context

- End-to-end architecture: `docs/01-architecture/README.md`
- AI onboarding overview: `docs/01-architecture/AI_Context.md`

## Process and working rules

- ExecPlan format/rules: `docs/PLANS.md`
- Commit quality expectations: `docs/THE_PERFECT_COMMIT.md`
- Active and historical implementation plans: `docs/12-plans/`
- Task specs used as implementation contracts: `docs/13-tasks/`
- Discoveries and exploration notes: `docs/14-understandings/`

## Docs tooling

- List docs and read hints: `npm run docs:list`
- Front matter requirements: `docs/docs-list.md`
- Build combined docs snapshot: `docs/docs-summary-script.md`
