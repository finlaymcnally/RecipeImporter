from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

_LIST_ITEM_RE = re.compile(r"^\s*(?:[-*\u2022]+|\d+[.)])\s+(.+)$", re.MULTILINE)
_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n")


@dataclass
class Atom:
    text: str
    kind: str  # 'paragraph', 'list_item', 'header'
    source_block_index: int
    sequence: int
    context_prev: Optional[str] = None
    context_next: Optional[str] = None
    container_start: Optional[int] = None
    container_end: Optional[int] = None
    container_header: Optional[str] = None


def split_text_to_atoms(
    text: str,
    block_index: int,
    *,
    sequence_offset: int = 0,
    container_start: int | None = None,
    container_end: int | None = None,
    container_header: str | None = None,
) -> List[Atom]:
    """Splits a block of text into atomic units (Atoms)."""
    blocks = _PARAGRAPH_SPLIT_RE.split(str(text))
    atoms: List[Atom] = []

    seq = sequence_offset

    def make_atom(content: str, kind: str) -> Atom:
        return Atom(
            text=content,
            kind=kind,
            source_block_index=block_index,
            sequence=seq,
            container_start=container_start,
            container_end=container_end,
            container_header=container_header,
        )

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        list_items = list(_LIST_ITEM_RE.finditer(block))
        if list_items:
            last_end = 0
            for match in list_items:
                start, end = match.span()
                pre_text = block[last_end:start].strip()
                if pre_text:
                    atoms.append(make_atom(pre_text, "paragraph"))
                    seq += 1

                atoms.append(make_atom(match.group(0).strip(), "list_item"))
                seq += 1
                last_end = end

            post_text = block[last_end:].strip()
            if post_text:
                atoms.append(make_atom(post_text, "paragraph"))
                seq += 1
        else:
            atoms.append(make_atom(block, "paragraph"))
            seq += 1

    return atoms


def contextualize_atoms(atoms: List[Atom]) -> List[Atom]:
    """Populates context_prev and context_next pointers for a list of atoms."""
    if not atoms:
        return []

    for i in range(len(atoms)):
        if i > 0:
            atoms[i].context_prev = atoms[i - 1].text
        if i < len(atoms) - 1:
            atoms[i].context_next = atoms[i + 1].text

    return atoms
