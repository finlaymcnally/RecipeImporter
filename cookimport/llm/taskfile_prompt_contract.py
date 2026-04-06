from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class TaskfilePromptSection:
    heading: str | None = None
    lines: tuple[str, ...] = ()


def section(
    *lines: str,
    heading: str | None = None,
) -> TaskfilePromptSection:
    return TaskfilePromptSection(
        heading=str(heading).strip() if heading is not None else None,
        lines=tuple(str(line) for line in lines if str(line).strip()),
    )


def render_taskfile_prompt(
    *sections: TaskfilePromptSection | None,
) -> str:
    rendered_sections: list[str] = []
    for prompt_section in sections:
        if prompt_section is None:
            continue
        section_lines = [str(line) for line in prompt_section.lines if str(line).strip()]
        if not section_lines and not str(prompt_section.heading or "").strip():
            continue
        rendered_lines: list[str] = []
        heading = str(prompt_section.heading or "").strip()
        if heading:
            rendered_lines.append(f"{heading}:")
        rendered_lines.extend(section_lines)
        rendered_sections.append("\n".join(rendered_lines))
    return "\n\n".join(rendered_sections)
