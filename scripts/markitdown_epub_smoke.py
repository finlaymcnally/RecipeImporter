#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cookimport.parsing.markitdown_adapter import convert_path_to_markdown


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert one EPUB to markdown using MarkItDown and print a short preview.",
    )
    parser.add_argument("epub_path", help="Path to an .epub file.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    path = Path(args.epub_path)

    if not path.exists() or not path.is_file():
        print(f"EPUB path not found: {path}", file=sys.stderr)
        return 1
    if path.suffix.lower() != ".epub":
        print(f"Expected an .epub file, got: {path}", file=sys.stderr)
        return 1

    try:
        markdown = convert_path_to_markdown(path)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"MarkItDown conversion failed: {exc}", file=sys.stderr)
        return 1

    lines = markdown.splitlines()
    print(f"chars: {len(markdown)}")
    print(f"lines: {len(lines)}")
    print("preview:")
    for line in lines[:30]:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
