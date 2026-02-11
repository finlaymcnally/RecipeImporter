---
summary: "Interactive benchmark now supports eval-only scoring when upload is declined."
read_when:
  - Extending C3imp interactive benchmark prompts
  - Debugging why benchmark can run without creating new Label Studio tasks
---

# Interactive Benchmark Eval-Only Fallback

- In `C3imp` interactive mode, choosing Benchmark no longer jumps straight to upload confirmation when existing prediction runs are available.
- If both freeform gold exports and prediction runs are found, the menu now asks for benchmark mode first:
  - `Score existing prediction run (no upload)`
  - `Generate fresh predictions + score (uploads to Label Studio)`
- If upload is accepted, flow is unchanged: it runs `labelstudio_benchmark(...)` and generates fresh prediction tasks before scoring.
- Eval-only mode prompts for an existing freeform gold export and an existing prediction run (`label_studio_tasks.jsonl`), then calls `labelstudio_eval(scope="freeform-spans", ...)`.
- This lets users re-score already-generated prediction tasks without another Label Studio write.
