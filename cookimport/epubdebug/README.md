# EPUB Debug CLI

`cookimport/epubdebug` powers the `cookimport epub ...` subcommands.
It reads EPUB container/package/spine data, reuses production block extraction and candidate detection, and writes debug artifacts for inspection.

Optional helper dependency:
- install via `python -m pip install -e '.[epubdebug]'`.
- `epub-utils` is currently pinned to pre-release `0.1.0a1`.
