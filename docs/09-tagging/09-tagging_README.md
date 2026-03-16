---
summary: "Inline recipe tagging for the current recipe-correction flow."
read_when:
  - When changing recipe tag output or normalization behavior
  - When updating the recipe correction contract to emit tags
---

# Tagging Section Reference

Tags are part of the main recipe-correction path now.

Use `docs/09-tagging/09-tagging_log.md` for the retained build/fix history and anti-loop notes for this surface.

Live code:

- `cookimport/llm/recipe_tagging_guide.py`
- `cookimport/llm/codex_farm_contracts.py`
- `cookimport/llm/codex_farm_orchestrator.py`
- `cookimport/staging/recipe_tag_normalization.py`
- `cookimport/staging/import_session.py`

Live contract:

- the recipe correction prompt emits raw `selected_tags`
- deterministic normalization cleans casing, punctuation, and separator variants
- final staged recipes store tags at `recipe.tags`
- intermediate JSON-LD mirrors the same ordered list into `keywords`
- in this repo, tags are metadata enrichment over the finalized recipe object and are projected into every written artifact that should carry them

Scope boundary:

- there is no separate tags subsystem anymore
- there are no tags-only commands, settings, or artifact trees
- no `tags/` artifact family or raw `raw/llm/.../tags/` outputs

Downstream contract guidance:

- `recipe.tags` is the canonical flat machine field for recipeimport outputs
- if richer provenance returns later, add it alongside `recipe.tags` as explicit metadata such as `recipe.tag_details`; do not hide it in prose notes
- JSON-LD should keep using `keywords` as the default projection field unless there is an explicit mapping to narrower schema.org fields

Cookbook integration boundary:

- Cookbook does not currently treat tags as part of canonical `RecipeDraftV1`
- canonical cookbook tags stay relational and are read/written separately from the draft payload
- import approval is the right seam to translate imported tag proposals into cookbook tag assignments

Prompt/token boundary:

- `cf-debug preview-prompts` still reconstructs only recipe, knowledge, and line-role prompts
- inline tag embedding does not create a separate prompt surface or add prompt input tokens by itself; accepted tags are normalized and projected into outputs after recipe correction
