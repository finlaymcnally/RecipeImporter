---
summary: "Tagging architecture/build/fix-attempt log to avoid repeated dead ends and circular debugging."
read_when:
  - When you are going in multi-turn circles on tagging behavior or implementation
  - When the human says "we are going in circles on this"
  - When you need prior tagging architecture versions, build attempts, or failed fixes before trying another change
---

# Tagging Log

Read this if you are going in multi-turn circles on the program, or if the human says "we are going in circles on this."
This file tracks tagging architecture versions, builds, fix attempts, and prior dead ends so we do not repeat them.

## Split Baseline (2026-02-19)

- `docs/09-tagging/09-tagging_README.md` is the source-of-truth for current tagging behavior and runtime contracts.
- `docs/09-tagging/09-tagging_log.md` is the running history of attempts and anti-loop notes.
- No prior tagging-specific attempt ledger existed in this folder before this split.

## Preserved Baseline Snapshot From Pre-split README

Preserving the pre-split baseline here so context is not lost:

- Auto-tagging code location and CLI wiring:
  - `cookimport/tagging/` via `tag-catalog` and `tag-recipes`.
- Core modules:
  - `catalog.py`: catalog models/loaders and fingerprinting
  - `signals.py`: signal extraction from recipe drafts
  - `rules.py`: deterministic tagging rules
  - `policies.py`: category policy enforcement
  - `engine.py`: scoring and selection
  - `db_write.py`: idempotent DB apply path
  - `llm_second_pass.py`: optional second-pass LLM scaffolding
- Operational docs:
  - `cookimport/tagging/README.md`
  - `docs/plans/I4.1-Auto-tag.md`

## Attempt Ledger

1. `2026-02-19` README/log split
- Established the two-file pattern in this section:
  - README for current behavior.
  - log for architecture/build/fix-attempt history.
