---
summary: "Inline recipe tagging for the current recipe-correction flow."
read_when:
  - When changing recipe tag output or normalization behavior
  - When updating the recipe correction contract to emit tags
---

# Tagging Section Reference

Tags are part of the main recipe-correction path and are normalized before staging writers run.

Use `docs/09-tagging/09-tagging_log.md` for the retained build/fix history and anti-loop notes for this surface.

Current code path:

- `cookimport/llm/recipe_tagging_guide.py`
- `cookimport/llm/codex_farm_contracts.py`
- `cookimport/llm/recipe_stage_shared.py`
- `cookimport/staging/recipe_tag_normalization.py`
- `cookimport/staging/import_session_flows/output_stage.py`
- `cookimport/staging/jsonld.py`
- `cookimport/staging/draft_v1.py`

Current contract:

- the recipe correction payload carries `tagging_guide.v3`, and recipe output returns raw `selected_tags`
- deterministic normalization owns casing, punctuation, separator cleanup, and de-duplication
- final cookbook3 drafts store the normalized ordered list at `recipe.tags`
- schema.org JSON-LD mirrors the same ordered list into `keywords`

Scope boundary:

- there is no separate tags stage anymore
- there are no tags-only commands, settings, or artifact trees
- no `tags/` artifact family or raw `raw/llm/.../tags/` outputs

Prompt/token boundary:

- `cf-debug preview-prompts` still reconstructs tagging only through the recipe prompt surface
- output projection and normalization happen after recipe correction; there is no separate tags prompt lane
