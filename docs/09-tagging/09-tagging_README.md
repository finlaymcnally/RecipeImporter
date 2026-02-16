---
summary: "Catalog-driven auto-tagging reference for draft-file and DB-backed tagging workflows."
read_when:
  - When changing auto-tagging rules, scoring, or category policies
  - When working on tag-catalog or tag-recipes CLI commands
---

# Tagging Section Reference

Auto-tagging code lives under `cookimport/tagging/` and is wired into the main CLI via `tag-catalog` and `tag-recipes` command groups.

## Core modules

- `catalog.py`: catalog models/loaders and fingerprinting
- `signals.py`: signal extraction from recipe drafts
- `rules.py`: deterministic tagging rules
- `policies.py`: category policy enforcement
- `engine.py`: scoring and selection
- `db_write.py`: idempotent DB apply path
- `llm_second_pass.py`: optional second-pass LLM scaffolding

## Operational docs

- Module-level quickstart:
  `cookimport/tagging/README.md`
- Implementation plan details:
  `docs/12-plans/I4.1-Auto-tag.md`
