# Core notes

- `RawArtifact` captures raw snippets for audit output; `staging.writer.write_raw_artifacts` writes them.
- `overrides_io.load_parsing_overrides` loads cookbook-specific `ParsingOverrides` from YAML/JSON sidecars.
- `progress_messages` centralizes safe `X/Y` status formatting (`task`/`item`/`config`/`phase`) for callback-driven spinners and dashboard status text.
