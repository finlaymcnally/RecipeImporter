from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence


def preview_text(text: object, *, max_chars: int = 160) -> str:
    rendered = " ".join(str(text or "").split())
    if len(rendered) <= max_chars:
        return rendered
    return rendered[: max(0, max_chars - 3)].rstrip() + "..."


def write_worker_hint_markdown(
    path: Path,
    *,
    title: str,
    summary_lines: Sequence[str] | None = None,
    sections: Sequence[tuple[str, Sequence[str] | str]] | None = None,
) -> None:
    lines: list[str] = [f"# {str(title or 'Worker hints').strip()}", ""]
    for line in summary_lines or ():
        cleaned = str(line or "").strip()
        if cleaned:
            lines.append(f"- {cleaned}")
    if summary_lines:
        lines.append("")
    for heading, content in sections or ():
        cleaned_heading = str(heading or "").strip()
        if not cleaned_heading:
            continue
        lines.append(f"## {cleaned_heading}")
        lines.append("")
        rendered_lines = _coerce_content_lines(content)
        if rendered_lines:
            lines.extend(rendered_lines)
        else:
            lines.append("- [none]")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _coerce_content_lines(content: Sequence[str] | str) -> list[str]:
    if isinstance(content, str):
        cleaned = str(content).strip()
        return [cleaned] if cleaned else []
    lines: list[str] = []
    for item in content:
        cleaned = str(item or "").strip()
        if not cleaned:
            continue
        if cleaned.startswith("- ") or cleaned.startswith("1. "):
            lines.append(cleaned)
        else:
            lines.append(f"- {cleaned}")
    return lines

