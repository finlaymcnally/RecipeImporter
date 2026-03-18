# Core notes

- `RawArtifact` captures raw snippets for audit output; `staging.writer.write_raw_artifacts` writes them.
- `overrides_io.load_parsing_overrides` loads cookbook-specific `ParsingOverrides` from YAML/JSON sidecars.
- `progress_messages` centralizes safe `X/Y` status formatting (`task`/`item`/`config`/`phase`) for callback-driven spinners and dashboard status text.
- `progress_messages` also owns the serialized callback payloads for worker activity and richer stage-progress snapshots, so CLI dashboards can keep worker/stage details without scraping every value back out of plain text.
- `executor_fallback` centralizes `process -> thread -> serial` executor resolution and shutdown helpers for sandbox-safe parallel fanout paths.
- `joblib_runtime` applies an early SemLock guard that sets `JOBLIB_MULTIPROCESSING=0` on restricted hosts to suppress repeated joblib serial-mode warnings.
