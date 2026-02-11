---
summary: "Parsing lane alignment with freeform golden-set taxonomy."
read_when:
  - Modifying chunk lane classification or benchmark label mapping
---

# Parsing Lane Alignment (Discovery)

- `cookimport/parsing/chunks.py` now routes narrative-like non-recipe prose to `ChunkLane.NOISE` instead of emitting `ChunkLane.NARRATIVE`.
- This keeps parsing outputs aligned with freeform labeling, where `NARRATIVE` is no longer a user-facing label and is treated as `OTHER`.
- `cookimport/staging/writer.py` reporting treats any legacy `ChunkLane.NARRATIVE` entries as noise so old artifacts remain readable without split statistics.
