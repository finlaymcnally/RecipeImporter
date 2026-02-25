---
summary: "Catalog-driven auto-tagging reference for draft-file and DB-backed tagging workflows."
read_when:
  - When changing auto-tagging rules, scoring, or category policies
  - When working on tag-catalog or tag-recipes CLI commands
---

# Tagging Section Reference

Auto-tagging code lives under `cookimport/tagging/` and is wired into the main CLI via `tag-catalog` and `tag-recipes` command groups.
For tagging architecture/build/fix-attempt history and anti-loop context, use `docs/09-tagging/09-tagging_log.md`.

## Core modules

- `catalog.py`: catalog models/loaders and fingerprinting
- `signals.py`: signal extraction from recipe drafts
- `rules.py`: deterministic tagging rules
- `policies.py`: category policy enforcement
- `engine.py`: scoring and selection
- `db_write.py`: idempotent DB apply path
- `llm_second_pass.py`: optional codex-farm-backed second pass for missing categories
- `codex_farm_tags_provider.py`: strict pass-5 shortlist/catalog validation and codex-farm IO boundary
- `orchestrator.py`: shared draft-folder tagging runner and stage pass integration

## Operational docs

- Module-level quickstart:
  `cookimport/tagging/README.md`
- Pass5 LLM tagging details:
  `docs/10-llm/tags_pass.md`
- Implementation plan details:
  `docs/plans/I4.1-Auto-tag.md`
- Version/build/fix-attempt history:
  `docs/09-tagging/09-tagging_log.md`
