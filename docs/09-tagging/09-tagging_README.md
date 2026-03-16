---
summary: "Inline recipe tagging for the current recipe-correction flow."
read_when:
  - When changing recipe tag output or normalization behavior
  - When updating the recipe correction contract to emit tags
---

# Tagging Section Reference

Tags are part of the main recipe-correction path now.

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

Scope boundary:

- there is no separate tags subsystem anymore
- there are no tags-only commands, settings, or artifact trees
- no `tags/` artifact family or raw `raw/llm/.../tags/` outputs
