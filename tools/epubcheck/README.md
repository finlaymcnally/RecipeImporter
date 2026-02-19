# EPUBCheck

Place `epubcheck.jar` (or another EPUBCheck jar) in this folder to enable:

- `cookimport epub validate <book.epub>`

You can also point the CLI at a custom jar path via `--jar` or `C3IMP_EPUBCHECK_JAR`.

For optional EPUB structure helper support:

- `source .venv/bin/activate && python -m pip install -e '.[epubdebug]'`
- (`epub-utils` is currently pinned as pre-release `0.1.0a1`.)
