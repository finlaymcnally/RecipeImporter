# EPUB Debug CLI

`cookimport/epubdebug` powers the `cookimport epub ...` subcommands.
It reads EPUB container/package/spine data, reuses production block extraction and candidate detection, and writes debug artifacts for inspection.

`cookimport epub race <book>.epub --out <dir>` runs the same deterministic auto-selection scorer used by stage (`--epub-extractor auto`) and writes `epub_race_report.json`.

Optional helper dependency:
- install via `python -m pip install -e '.[epubdebug]'`.
- `epub-utils` is currently pinned to pre-release `0.1.0a1`.
