---
summary: "LLM integration notes and boundaries for optional repair passes in the import pipeline."
read_when:
  - When enabling or modifying LLM-assisted repair behavior
  - When auditing deterministic-vs-LLM fallback boundaries
---

# LLM Section Reference

LLM integrations are optional and live under `cookimport/llm/`.

## Core code

- `cookimport/llm/client.py`
- `cookimport/llm/prompts.py`
- `cookimport/llm/repair.py`

## Design and rollout plan

- `docs/12-plans/I6.1-integrate-LLM.md`

## Important boundary

Primary stage imports remain deterministic by default; LLM behavior should be explicitly gated and auditable.
