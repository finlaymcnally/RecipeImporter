---
summary: "LLM architecture/build/fix-attempt log used to avoid repeating failed paths."
read_when:
  - When you are going in multi-turn circles on LLM behavior or implementation
  - When the human says "we are going in circles on this"
  - When you need prior architecture versions, builds, or fix attempts before trying another change
---

# LLM Build and Fix Log

Read this file when troubleshooting loops across turns, or when someone says "we are going in circles on this."

## How to use this log

- Capture architecture versions, build attempts, and fix attempts before trying a new approach.
- Include why each attempt worked or failed to prevent repeating dead ends.

## Entries

### 2026-02-19_15.49.52 split README vs log

- Created `10-llm_log.md` to keep architecture/build/fix-attempt history separate from reference documentation.
- Kept `10-llm_README.md` focused on current-state LLM reference and linked this log from it.
