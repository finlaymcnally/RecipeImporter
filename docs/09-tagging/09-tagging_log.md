---
summary: "Tagging architecture/build/fix-attempt log for the current inline recipe-tagging surface."
read_when:
  - When tagging behavior or contracts start going in circles
  - When deciding whether tags belong in the recipe prompt, normalized staged outputs, or report metadata
---

# Tagging Log

This file keeps the still-relevant history for the current inline tagging model.

## 2026-03-16 inline tagging contract consolidation

### 2026-03-16_15.10.33 tagging as recipe-metadata enrichment

Problem captured:
- tagging logic and projection surfaces had been split across stages, which encouraged sidecar-only thinking and late output mutation

Durable decisions:
- treat tagging as metadata enrichment over the finalized recipe object
- write the accepted ordered tag list to `recipe.tags`
- mirror the same list into JSON-LD `keywords`
- if richer tag provenance is needed later, add an explicit metadata field rather than encoding tags in prose notes

Anti-loop note:
- do not rebuild a tags-only sidecar pipeline just to project tags into final outputs

### 2026-03-16_15.47.58 prompt-preview boundary

Problem captured:
- tag embedding was easy to misread as a new prompt-cost surface

Durable decisions:
- prompt preview remains recipe + knowledge + line-role only
- embedding accepted tags back into outputs does not by itself change prompt input tokens

Anti-loop note:
- if prompt cost appears to move after a tagging change, prove whether the prompt builders changed or only the output projection changed

### 2026-03-16_15.54.02 burn-the-boats inline model

Problem captured:
- the standalone tags pipeline duplicated recipe text, ran too late, and created extra CLI/settings/docs surface area

Durable decisions:
- recipe tagging belongs inside the single recipe-correction pipeline
- keep only a lightweight deterministic normalization pass afterward
- the standalone tags pipeline, tags-only CLI/settings, and raw tags artifact tree should stay deleted

Anti-loop note:
- if a fix proposal wants separate tags prompts "for flexibility," check whether it is just reintroducing duplicated recipe text and late projection
