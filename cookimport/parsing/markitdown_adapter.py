from __future__ import annotations

from pathlib import Path


def convert_path_to_markdown(path: Path) -> str:
    """Convert a document path to markdown text with MarkItDown."""
    try:
        from markitdown import MarkItDown
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "EPUB extractor 'markitdown' requires the `markitdown` package. "
            "Install project deps (`pip install -e .[dev]`) and retry."
        ) from exc

    converter = MarkItDown(enable_plugins=False)
    result = converter.convert(str(path))
    markdown = getattr(result, "text_content", None)
    if not isinstance(markdown, str):
        raise RuntimeError("MarkItDown conversion did not return markdown text_content.")
    return markdown
