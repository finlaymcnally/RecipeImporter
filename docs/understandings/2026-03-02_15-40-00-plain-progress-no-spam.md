## 2026-03-02_15.40.00: quiet plain progress output for benchmark runs

- `_run_with_progress_status` now renders plain progress updates as a single in-place line when stdout is a TTY, instead of printing a new line for every tick/message. This keeps a stable summary visible during long codex-farm stages.
- `SubprocessCodexFarmRunner` now filters progress-event lines out of stderr warnings and only warns on non-progress stderr content, so normal codex-farm queue/run chatter is no longer emitted as terminal spam.
- `SubprocessCodexFarmRunner` now also parses legacy `run=<id> queued=... running=... done=...` progress lines and turns them into callback updates, plus previewing active `input_path` names from JSON progress events (`active ...`) so users can see what each worker slot is processing.
