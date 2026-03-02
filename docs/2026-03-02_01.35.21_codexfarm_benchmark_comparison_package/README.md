# CodexFarm Benchmark Comparison Package

Created: 2026-03-02_01.35.21

This package contains the two requested recent CodeX Farm benchmark runs and the most recent non-CodeX baseline runs for the same two books.

## Runs included

| Folder | Source run | Workbook | LLM pipeline | Overall line accuracy | Macro F1 (excluding OTHER) | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `runs/seaandsmoke_codex` | `data/golden/benchmark-vs-golden/2026-03-02_01.01.06` | `seaandsmokecutdown` | `codex-farm-3pass-v1` | `0.299` | `0.372` | SeaAndSmoke CODEX run |
| `runs/thefoodlab_codex` | `data/golden/benchmark-vs-golden/2026-03-02_01.11.21` | `thefoodlabcutdown` | `codex-farm-3pass-v1` | `0.428` | `0.290` | TheFoodLab CODEX run |
| `runs/seaandsmoke_pre` | `data/golden/benchmark-vs-golden/2026-02-26_17.47.33` | `seaandsmokecutdown` | `off` | `0.303` | `0.297` | Pre-CODEX baseline |
| `runs/thefoodlab_pre` | `data/golden/benchmark-vs-golden/2026-03-02_01.34.17` | `thefoodlabcutdown` | `off` | `0.360` | `0.263` | Pre-CODEX baseline |

Notes:

- SeaAndSmoke had no later non-CODEX run after `2026-03-02_01.01.06`, so the nearest baseline is `2026-02-26_17.47.33`.
- TheFoodLab had a later non-CODEX run at `2026-03-02_01.34.17`, which is used as baseline here.

## Exact prompts sent to CodeX Farm

For each CodeX run, all prompt input payloads are copied verbatim from `prediction-run/raw/llm/<run_id>/<pass>_*/in/*.json`.

- SeaAndSmoke pass file counts:
  - `pass1_chunking`: 19 files
  - `pass2_schemaorg`: 19 files
  - `pass3_final`: 19 files
- TheFoodLab pass file counts:
  - `pass1_chunking`: 62 files
  - `pass2_schemaorg`: 42 files
  - `pass3_final`: 39 files

Manifest files list those exact JSON payload filenames:

- SeaAndSmoke
  - Inputs: `runs/seaandsmoke_codex/prompt_inputs_manifest.txt`
  - Outputs: `runs/seaandsmoke_codex/prompt_outputs_manifest.txt`
- TheFoodLab
  - Inputs: `runs/thefoodlab_codex/prompt_inputs_manifest.txt`
  - Outputs: `runs/thefoodlab_codex/prompt_outputs_manifest.txt`

## Why this answers your question

- SeaAndSmoke
  - Baseline avg line accuracy: `0.303`
  - CodeX avg line accuracy: `0.299`
  - Difference: `-0.004`
- TheFoodLab
  - Baseline avg line accuracy: `0.360`
  - CodeX avg line accuracy: `0.428`
  - Difference: `+0.068`

The outputs were not the same as the input payloads, because `pass*_in` files are the model prompts and `pass*_out` files are model responses. This package includes both, so you can compare prompt/response pairs directly.

## Suggested comparison commands

```bash
# SeaAndSmoke pass1 prompt payloads
sed -n '1,40p' runs/seaandsmoke_codex/prompt_inputs_manifest.txt

# TheFoodLab pass1 prompt payloads
sed -n '1,40p' runs/thefoodlab_codex/prompt_inputs_manifest.txt

# Compare run-level manifests side-by-side
diff -u runs/seaandsmoke_pre/run_manifest.json runs/seaandsmoke_codex/run_manifest.json
```
