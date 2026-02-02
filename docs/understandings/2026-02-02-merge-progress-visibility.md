---
summary: "Merge work runs on the main process; dashboard now exposes merge status."
read_when:
  - When debugging progress stalls during split EPUB/PDF merges
---

Split EPUB/PDF jobs finish in workers, but the main process performs the merge. That can leave worker lines idle while the merge is still busy. The CLI now surfaces a MainProcess status line during merges and advances the job progress before the merge work so the UI reflects ongoing activity.
